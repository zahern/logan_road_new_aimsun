      subroutine penalty_calculation(l)
c --  
c -- This subroutine calculates the average delay at each intersection, for
c -- each approach and each movement.
c --
c -- This subroutine is called from loop (to initialize the penalties) and
c -- form vehicle_transfer every simulation interval.
c --  
c -- INPUT :
c -- 
c -- OUTPUT : 
c --   penalties (in forward star and backward star representations).
c --   the forward star penalties are used in the SO calculations.
c --   the backward star penalties are used in the K-shortest path, UE and SO.
c -- 
      use muc_mod
      use vector_mod
      use LinkList_mod
c --  
c --  penalty calculation is to convert delay to penalty array procedure
c --  1. scan mtxj array, if the vehicle is in queue, check nexlink
c --  2. cumulate all directions' vehicles
c --  3. use average flow rate to calculate the delay
c --  4. convert the data to penalty structure
c --
c --  move is use to identify  different movements
c --  1: left turn
c --  2: straight 
c --  3: right
c --  4: others
c  -- 6: U turn
c --
c -- initialization of delaystep,indelay
c --
      type(linkstruct),pointer                 :: pass
      allocate(pass)
!      if(l.eq.1) then
!      do i=1,noofarcs
!         do ii=1,nu_de
!            delaystep(i,ii)=MaxFlowRate(i)
!            if(node(idnod(i),2).eq.4) delaystep(i,ii)=MaxFlowRate(i)/2
!            if(node(idnod(i),2).eq.5) delaystep(i,ii)=MaxFlowRate(i)/2
!            delayleft(i,ii)=(MaxFlowRate(i)/2.0)
!            if(node(idnod(i),2).eq.4) delayleft(i,ii)=MaxFlowRate(i)/4
!            if(node(idnod(i),2).eq.5) delayleft(i,ii)=MaxFlowRate(i)/4
!         end do
!      end do
!      endif
c --
c --
c --
      turnveh(:,:)=0
c --
c -- Calculate the turnveh array : the number of vehicles in the queue on link i which are making a specific movement.
c -- 	 
      do i=1,noofarcs

         p_mtxj_value=>LinkVehList(i)
         do while(associated(p_mtxj_value%next_veh))
           id_veh=p_mtxj_value%veh
           if(id_veh.gt.0) then
             ttemp = (l-1)*tii
             if(nexlink(id_veh).lt.1) then
               icu=i
	         Itp1= icurrnt(id_veh)+1
	         Itp2 = 0
	         inode = nint(VhcAtt_Value(id_veh,Itp1,1))
               do k=backpointr(inode),backpointr(inode+1)-1
                  if(idnod(i).eq.UNodeOfBackLink(k)) then
                    nexlink(id_veh)=BackToForLink(k)
                    Itp2 = 1
                    exit
                  endif
               enddo
               if(Itp2.lt.1) then
	  write(911,*)'Penalty Calculation when finding next link'
	          stop
	         endif   
		   endif
c		   call getlink(ttemp,id_veh,i)
             nl=nexlink(id_veh)
            if(idnod(nexlink(id_veh)).ne.
     *         destination(MasterDest(jdest(id_veh))))then
              do k=1,llink(i,nu_mv+1)
                if(llink(i,k).eq.nl) then
                  moveturn=move(i,k)
				exit
                 endif
              enddo   
              if(moveturn.gt.6.or.moveturn.lt.1) then
c	          print *, 'moveturn error in penalty_calcluation'
                moveturn=1
              elseif(moveturn.eq.6) then
			  moveturn=1
              endif
              turnveh(i,moveturn)=turnveh(i,moveturn)+1
	       endif
            endif 
	      p_mtxj_value=>p_mtxj_value%next_veh
         enddo
      enddo
c  -- turnveh will converted into time, need to keep this array for marginal use

c --  turnveh is calculated in vehicle_transfer 
      turnvehso(:,:) = turnveh(:,:)
c --
c --
c --
c -- delay calculation
c -- 
c -- delaystep is used to store the outflow for the last
c -- nu_de simulation intervals.
c -- The counter for the stored intervals is in the indelay
c -- array. When indelay for a specific link reaches nu_de, reset to 1.
c --
c --
      do 289 i=1,noofarcs

         indelay=indelay+1
         if(indelay.eq.(nu_de+1)) indelay=1
         tmp=MaxFlowRate(i)*tii*60
         if(vehicle_queue(i).ge.tmp) then
           delaystep(i,indelay)=real(outflow(i)/(tii*60))
         else
           delaystep(i,indelay)=MaxFlowRate(i)
         endif
c  --
c  -- for left turn movement  
c  --
         tmp=left_capacity(i)*tii*60
         if(turnveh(i,1).ge.tmp) then
           delayleft(i,indelay)=real(outleft(i)/(tii*60))
         else
           delayleft(i,indelay)=left_capacity(i)
         endif
c  --
c  --
         aveoutflow(i)=0
         do ii=1,nu_de
           aveoutflow(i)=aveoutflow(i)+delaystep(i,ii)
         end do
           aveoutflow(i)=aveoutflow(i)/nu_de
           if(aveoutflow(i).lt.0.001) aveoutflow(i)=0.0001 
c  --
c  -- calculate left average flow rate
c  --
         aveoutleft(i)=0
         do ii=1,nu_de
           aveoutleft(i)=aveoutleft(i)+delayleft(i,ii)
         end do
         aveoutleft(i)=aveoutleft(i)/nu_de
         if(aveoutleft(i).lt.0.001) aveoutleft(i)=0.001 
c --
c -- itmp : number of left turning vehicles in the queue on link i.
c -- iveh_remain : the queue length - itmp
c --
         itmp=turnveh(i,1)
         iveh_remain=vehicle_queue(i)-itmp
c --
c -- turnveh is now converted into time
c --
         turnveh(i,1)=itmp/(aveoutleft(i)*60)
         if(turnveh(i,1).lt.0.002) turnveh(i,1)=0.002
         delayother=(iveh_remain)/(aveoutflow(i)*60)
         if(delayother.lt.0.001) delayother=0.001
c --
c --         
         do ii=2,nu_mv
           turnveh(i,ii)=delayother
         end do
289   continue
c --  
c --  convert the delay to penalty
c --  all the delay is in turnveh(i,j).
c --
c -- initialize the forward star penalties
c -- The openalty is the forward penalty and it is used in the SO marginals
c --
 
      openalty(:,:)=PenForPreventMove

c --
c -- calculate the forward star penalties (openalty)
c --
      do i=1,noofarcs
        do j=1,move(i,nu_mv+1)

c --
c --  check if the movement is not 
c --  allowed for due to the signal phasing,
c --  then consider a very high penalty, otherwise, use the
c --  value for the delay
c --
!          if(SignalPreventFor(i,j).ne.1) then

! To take into account movement definition from movement.dat
      if(SignalPreventFor(i,j).eq.0.and. GeoPreventFor(i,j).eq.0) then !allowed

            if(move(i,j).eq.1.or.move(i,j).eq.6) then
!              if(.not.bay(i))  then

              if(bay(i).eq.0)  then

			  openalty(i,j)=turnveh(i,1)+turnveh(i,2)
              else
			  openalty(i,j)=turnveh(i,1)
	        endif
            else
              openalty(i,j)=turnveh(i,2)
            endif
	      if(openalty(i,j).gt.10) openalty(i,j)=10
          else
	         openalty(i,j)=PenForPreventMove  ! defined muc_mod_td
		

          endif
		
         enddo
       enddo  
c --
c -- initialize the backward star penalties
c --
  
      penalty(:,:)=PenForPreventMove
  
c --
c -- calculate the penalties in the backward star 
c --  
      do i=1,noofarcs


        nodeup=iunod(i)
        ip=ForToBackLink(i)
        do j=1,inlink(i,nu_mv+1)
          il=inlink(i,j)


!          if(SignalPreventBack(ip,j).ne.1) then

! To take into account movement definition from movement.dat
      if(SignalPreventBack(ip,j).eq.0.and. GeoPreventBack(ip,j).eq.0)
     +	then


            if(movein(i,j).eq.1.or.movein(i,j).eq.6) then 

!              if(.not.bay(i)) then

              if(bay(i).eq.0)  then


		      penalty(ip,j)=turnveh(il,1)+turnveh(il,2)
              else
		      penalty(ip,j)=turnveh(il,1)
	        endif
            else
             penalty(ip,j)=turnveh(il,2)
            endif
            if(penalty(ip,j).gt.10) penalty(ip,j)=10
          else

	         penalty(ip,j)=PenForPreventMove  ! defined muc_mod_td
			 if(link_iden(i).eq.99) then
					penalty(ip,j) = 0



			endif


	    endif

!	write(91119,*) nodenum(iunod(i)),nodenum(idnod(i)),j,
!     + nodenum(iunod(il)),nodenum(idnod(il)),penalty(ip,j)


        enddo
      enddo
      deallocate(pass)
      return
      end
