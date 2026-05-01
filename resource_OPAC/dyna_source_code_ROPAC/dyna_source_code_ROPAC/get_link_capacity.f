      subroutine get_link_capacity()
c --
c -- This subroutine is called from the main_loop
c -- This subrourine calls get_left_capacity and adjust_saturation.
c --
      use muc_mod
      real MFRtmp
      logical IMajor
c --
c --  Initialize the time-dependent link arrays. (i.e. the arrays which are updated each simulation interval)

c	print *,right_capacity(111),iunod(111),idnod(111)
c      do j=1,llink(111,nu_mv+1)
c           print *, green(111,j)
c      enddo
c	pause
c --
      do i=1,noofarcs
        captot(i)=0.0
        if(xl(i).lt.0.001)then
          c(i)=cmax(i)
        else 
          c(i)=min(cmax(i),(partotal(i))/xl(i))
        endif
      enddo   
c --
c --
      do 10 i=1,noofarcs

	  if(link_iden(i).lt.99)then ! only for regular links
c --
c -- Calculate the maxgreen: the maximum green time for the current link. 
c --
        greenmax=0.0
        do j=1,llink(i,nu_mv+1)
           if(green(i,j).gt.greenmax) greenmax=green(i,j)
        enddo
c --
c -- NOTE : the function anint calculates the nearest integer number 
c --
!           captot(i)=nint(greenmax*MaxFlowRate(i))
c --
c -- calculate the left capacity
c -- 1. identify the left turn movement
c -- 2. check the left table
c -- table : leftcap and leftcap2 (from the input file leftcap.dat (fort.48))
c --
c -- left_capacity = link_capacity (if there is no opposing traffic)
c --

c --  computed adjusted Maximal Service Flow Rate based on Heavy Vehicle factor
c --  based on HCM 98 eq 3-2, pg 3-10
      Fhv = 1.0/(1+Truckpct(i)*(DynPCE(i)-1))
      MaxFlowRate(i)=MaxFlowRateOrig(i)*Fhv
      captot(i)=nint(greenmax*MaxFlowRate(i))
!
	MFRtmp = MaxFlowRate(i)



c --
c -- Check for signalized intersections (pretimed, actuated, or adaptive)
c -----------------------------------------------------------------
      if(node(idnod(i),2).eq.4.or.node(idnod(i),2).eq.5.or.
     +	  node(idnod(i),2).eq.9) then !pre-timed or actuated
c -----------------------------------------------------------------
c --
c -- This part gets the value for opp_link.
c -- NOTE : the difference between opp_link and opp_link1 is 
c -- opp_linkP : is the phsyical opposing link (from the network structure)
c -- opp_linkS : is the physical opposing link which has green time for its
c --            through movement during the same phase as the left turn movement
c --            for the current link.
c --
c -- jakm : is a temprary variable to keep the opp_linkP(i) value.
c --
	  jakm=opp_linkP(i)
	  opp_linkS(i)=0
c --
c -- check if there is a physical opposing link.  If not, skip this part.
c --
          if(jakm.gt.0) then
	      do k=1,llink(jakm,nu_mv+1)
		    if(green(jakm,k).ne.0) then
                jk=llink(jakm,k)
                if(iunod(jk).eq.idnod(i).and.idnod(jk).eq.iunod(i)) then
	             opp_linkS(i)=jakm
	             exit
                endif  
	        endif
	      end do
          endif
c  --
c -- The subroutine get_left_capacity is called only when there is an 
c -- opposing link which has green time in the same phase as the left
c -- turn movement on link i.
c --
c -- The saturation flow rate of through and right traffic 
c -- will be changed due to the left turn traffic on the same link.
c -- call the subroutine adjust_saturation to reduce the flow rate.
c --


         do j=1,move(i,nu_mv+1)
           if(move(i,j).eq.1) then
             if(green(i,j).gt.0) 
     *       call adjust_saturation(i,MFRtmp,t,1)
             if(opp_linkS(i).gt.0) then
		      call get_left_capacity(i,1) ! with opposing links
	       else 
	          call get_left_capacity(i,0) ! without opposing links
	       endif
	       exit
           endif
         end do

! --                                   determined above using some special lookup table information
c -- MFRtmp is the adjusted through capacity (from adjust_saturation).
c --
         do j=1,llink(i,nu_mv+1)
c  --
c  -- adjust capacity in order to reflect left cap
c  --
            if(move(i,j).eq.1) then
!              
!			capacity(i,j)=green(i,j)*left_capacity(i)
! comment out the above line, because we do not use capacity(i,j) in vehicle moving module for left-turn movement
              
		left_capacity(i)=green(i,j)*left_capacity(i)		


              tmp=left_capacity(i)-ifix(left_capacity(i))
              if(tmp.gt.0.0001) then
			  call random_number(r5)
            if(r5.le.tmp) left_capacity(i)=ifix(left_capacity(i))+1
	        endif


!              tmp=green(i,j)*left_capacity(i)-ifix(capacity(i,j))
!              if(tmp.gt.0.0001) then
!			  call random_number(r5)
!                if(r5.le.tmp) capacity(i,j)=ifix(capacity(i,j))+1
!	        endif


!*******************for dyna 930.7************************************************		 
		 elseif(move(i,j).eq.3) then					!right turn 
		 right_capacity(i)=green(i,j)*MFRtmp 
		 tmp=green(i,j)*MFRtmp-ifix(right_capacity(i))
              if(tmp.gt.0.0001) then
                call random_number(r5)
         if(r5.le.tmp) right_capacity(i)=ifix(right_capacity(i))+1
              endif	
!***********************end of addition********************************************            
	

            else ! not a left turn movement
              capacity(i,j)=green(i,j)*MFRtmp
              tmp=green(i,j)*MFRtmp-ifix(capacity(i,j))
              if(tmp.gt.0.0001) then
                call random_number(r5)
                if(r5.le.tmp) capacity(i,j)=ifix(capacity(i,j))+1
              endif
            endif

         enddo


! finish pre-timed or actuated

c -----------------------------------------------------------------
      elseif(node(idnod(i),2).eq.1) then ! for freeway, use Max Service Flow rate
c -----------------------------------------------------------------
         call adjust_saturation(i,MFRtmp,t,0)

! --  determined above using some special lookup table information
c -- MFRtmp is the adjusted through capacity (from adjust_saturation).
c --
         do j=1,llink(i,nu_mv+1)
              capacity(i,j)=(green(i,j)*MFRtmp)
              tmp=green(i,j)*MFRtmp-ifix(capacity(i,j))
              if(tmp.gt.0.0001) then
                call random_number(r5)
                if(r5.le.tmp) capacity(i,j)=ifix(capacity(i,j))+1
              endif
         enddo


! Starting 4-way Stop Sign
c -----------------------------------------------------------------  
      elseif(node(idnod(i),2).eq.3) then
c -----------------------------------------------------------------
         do j=1,move(i,nu_mv+1)
           if(move(i,j).eq.1) then
             if(green(i,j).gt.0) then
		     call adjust_saturation(i,MFRtmp,t,1)
	         exit
	       endif
           endif
         end do


	
		captot(i)= 0
	    capacity(i,:) = 0


         do j=1,llink(i,nu_mv+1)
c  --
c  -- adjust capacity in order to reflect left cap
c  --
!          if(move(i,j).eq.1) then ! Left turn movement
!            capacity(i,j)=
!     *      (green(i,j)*nlanes(i)*
!     *           StopCap4w(min(4,total_count(i)+1),1)/3600.0)
!            tmp=green(i,j)*nlanes(i)*
!     *           StopCap4w(min(4,total_count(i)+1),1)/3600.0
!     *          -ifix(capacity(i,j))
!            if(tmp.gt.0.0001) then
!             call random_number(r5)
!             if(r5.le.tmp) capacity(i,j)=ifix(capacity(i,j))+1
!            endif


! We use left_capacity() for left turn movement

	if(move(i,j).eq.1) then

            left_capacity(i)=
     *      (green(i,j)*nlanes(i)*
!***********************


!     *           StopCap4w(min(4,total_count(i)+1),1)/3600.0)
     *           StopCap4w(min(4,total_count(i)+1),2)/3600.0)
            tmp=green(i,j)*nlanes(i)*
!     *           StopCap4w(min(4,total_count(i)+1),1)/3600.0
     *           StopCap4w(min(4,total_count(i)+1),2)/3600.0     
     *          -ifix(left_capacity(i))
!*********************************   
  
            if(tmp.gt.0.0001) then
             call random_number(r5)
             if(r5.le.tmp) left_capacity(i)=ifix(left_capacity(i))+1
            endif


!*******************for dyna 930.7************************************************		 
	elseif(move(i,j).eq.3) then !right turn
            right_capacity(i)=
     *      (green(i,j)*nlanes(i)*
     *           StopCap4w(min(4,total_count(i)+1),3)/3600.0)
            tmp=green(i,j)*nlanes(i)*
     *           StopCap4w(min(4,total_count(i)+1),3)/3600.0
     *          -ifix(right_capacity(i))
            if(tmp.gt.0.0001) then
             call random_number(r5)
             if(r5.le.tmp) right_capacity(i)=ifix(right_capacity(i))+1
            endif 


	elseif(move(i,j).eq.2) then !through turn
      capacity(i,j)=
     *      (green(i,j)*nlanes(i)*
!***********************


!     *      (StopCap4w(min(4,total_count(i)+1),2))/3600.0)
     *      (StopCap4w(min(4,total_count(i)+1),1))/3600.0)
            tmp=green(i,j)*nlanes(i)*
!*      (StopCap4w(min(4,total_count(i)+1),2))/3600.0     
     *      (StopCap4w(min(4,total_count(i)+1),1))/3600.0
     *          -ifix(capacity(i,j))
!**********************************
            if(tmp.gt.0.0001) then
             call random_number(r5)
             if(r5.le.tmp) capacity(i,j)=ifix(capacity(i,j))+1
            endif


          else ! take average value of left and right for movements other1 and other 2
            capacity(i,j)=
     *      (green(i,j)*nlanes(i)*
     *      (StopCap4w(min(4,total_count(i)+1),1)+
     *       StopCap4w(min(4,total_count(i)+1),3))/2.0/3600.0)
            tmp=green(i,j)*nlanes(i)*
     *      (StopCap4w(min(4,total_count(i)+1),1)+
     *       StopCap4w(min(4,total_count(i)+1),3))/2.0/3600.0
     *          -ifix(capacity(i,j))
            if(tmp.gt.0.0001) then
             call random_number(r5)
             if(r5.le.tmp) capacity(i,j)=ifix(capacity(i,j))+1
            endif
          endif
!******************************End of addition*************************************



!            capacity(i,j)=
!     *      (green(i,j)*nlanes(i)*
!     *      (StopCap4w(min(4,total_count(i)+1),2)+
!     *       StopCap4w(min(4,total_count(i)+1),3))/2.0/3600.0)
!            tmp=green(i,j)*nlanes(i)*
!     *      (StopCap4w(min(4,total_count(i)+1),2)+
!     *       StopCap4w(min(4,total_count(i)+1),3))/2.0/3600.0
!     *          -ifix(capacity(i,j))
!            if(tmp.gt.0.0001) then
!             call random_number(r5)
!             if(r5.le.tmp) capacity(i,j)=ifix(capacity(i,j))+1
!            endif
!          endif
!****************************** dend of deletion********* 

        

	  captot(i)=max(captot(i),capacity(i,j),left_capacity(i),
     *	right_capacity(i))

         enddo

c -----------------------------------------------------------------
      elseif(node(idnod(i),2).eq.6) then ! two-way stops
c -----------------------------------------------------------------
         do j=1,move(i,nu_mv+1)
           if(move(i,j).eq.1) then
             if(green(i,j).gt.0)  then
              call adjust_saturation(i,MFRtmp,t,1)
	        exit
	       endif
           endif
         end do
!    determine the average flow on the major approaches

         do ik = 1, SignCount
           if(idnod(i).eq.SignData(ik)%node) then
             IndSig = ik
	       exit
	     endif
	   enddo

         IMajor=.False.
	   do iMM = 1, SignData(IndSig)%NofMajor
	     if(i.eq.SignApprh(IndSig)%major(iMM)) then ! link i is the major appraoch
             IMajor=.True.
	       exit
           endif
         enddo

         if(IMajor) then !link i is major approach
           do j=1,llink(i,nu_mv+1)
              capacity(i,j)=(green(i,j)*MFRtmp)
              tmp=green(i,j)*MFRtmp-ifix(capacity(i,j))
              if(tmp.gt.0.0001) then
                call random_number(r5)
                if(r5.le.tmp) capacity(i,j)=ifix(capacity(i,j))+1
              endif
           enddo


         else !link i is minor approach
	   


! Count averate flow rate on major approaches	   
	   TotMJflow = 0.0
! 	   do iip = 1, SignData(IndSig)%NofMinor
 	   do iip = 1, SignData(IndSig)%NofMajor
!	   	     LLT = SignApprh(IndSig)%minor(iip)
	   	     LLT = SignApprh(IndSig)%major(iip)
           TotMJflow=TotMJflow+aveoutflow(LLT)*3600/nlanes(LLT)
	   enddo
!         AvgMJflow = TotMJflow/SignData(IndSig)%NofMinor
         AvgMJflow = TotMJflow/SignData(IndSig)%NofMajor
         do ih = 1, level2N
           if(AvgMJflow.lt.stopcap2wiND(ih)) then
	       IndCap = ih
	       exit
	     endif
	   enddo


		
		captot(i)= 0
	    capacity(i,:) = 0
      

	   do j=1,llink(i,nu_mv+1)  ! Left turn movement
         if(move(i,j).eq.1) then
!           capacity(i,j)=
!     *     (green(i,j)*nlanes(i)*StopCap2w(IndCap,1)/3600.0)
!             tmp=green(i,j)*nlanes(i)*StopCap2w(IndCap,1)/3600.0-
!     *       ifix(capacity(i,j))
!             if(tmp.gt.0.0001) then
!               call random_number(r5)
!               if(r5.le.tmp) capacity(i,j)=ifix(capacity(i,j))+1


! We use left_capacity() for left turn movement

           left_capacity(i)=
     *     (green(i,j)*nlanes(i)*StopCap2w(IndCap,1)/3600.0)
             tmp=green(i,j)*nlanes(i)*StopCap2w(IndCap,1)/3600.0-
     *       ifix(left_capacity(i))
             if(tmp.gt.0.0001) then
               call random_number(r5)
               if(r5.le.tmp) left_capacity(i)=ifix(left_capacity(i))+1

             endif


!*******************for dyna 930.7************************************************		 
	elseif(move(i,j).eq.3) then !right turn
            right_capacity(i)=
     *      (green(i,j)*nlanes(i)*
     *           StopCap2w(min(4,total_count(i)+1),3)/3600.0)
            tmp=green(i,j)*nlanes(i)*
     *           StopCap2w(min(4,total_count(i)+1),3)/3600.0
     *          -ifix(right_capacity(i))
            if(tmp.gt.0.0001) then
             call random_number(r5)
             if(r5.le.tmp) right_capacity(i)=ifix(right_capacity(i))+1
            endif 


	elseif(move(i,j).eq.2) then !through turn
      capacity(i,j)=
     *      (green(i,j)*nlanes(i)*
     *      (StopCap2w(min(4,total_count(i)+1),2))/3600.0)
            tmp=green(i,j)*nlanes(i)*
     *      (StopCap2w(min(4,total_count(i)+1),2))/3600.0
     *          -ifix(capacity(i,j))
            if(tmp.gt.0.0001) then
             call random_number(r5)
             if(r5.le.tmp) capacity(i,j)=ifix(capacity(i,j))+1
            endif

          else ! take average value of left and right for movements other1 and other 2
            capacity(i,j)=
     *      (green(i,j)*nlanes(i)*
     *      (StopCap2w(min(4,total_count(i)+1),1)+
     *       StopCap2w(min(4,total_count(i)+1),3))/2.0/3600.0)
            tmp=green(i,j)*nlanes(i)*
     *      (StopCap2w(min(4,total_count(i)+1),1)+
     *       StopCap2w(min(4,total_count(i)+1),3))/2.0/3600.0
     *          -ifix(capacity(i,j))
            if(tmp.gt.0.0001) then
             call random_number(r5)
             if(r5.le.tmp) capacity(i,j)=ifix(capacity(i,j))+1
            endif
          endif
!******************************End of addition*************************************



!         else ! take average value of through and right for movements other than left
!               capacity(i,j)=(green(i,j)*nlanes(i)*
!     *         (StopCap2w(IndCap,2)+StopCap2w(IndCap,3))/2.0/3600.0)
!               tmp=green(i,j)*nlanes(i)*(StopCap2w(IndCap,2)+
!     *             StopCap2w(IndCap,2))/2.0/3600.0 -ifix(capacity(i,j))
!!               if(tmp.gt.0.0001) then
 !                call random_number(r5)
 !                if(r5.le.tmp) capacity(i,j)=ifix(capacity(i,j))+1
 !              endif
 !        endif
!********************************************end of deletion*********************
         
	   
	  captot(i)=max(captot(i),capacity(i,j),left_capacity(i),
     *	right_capacity(i))


	   enddo
         endif !.not.IMajor



c -----------------------------------------------------------------
      elseif(node(idnod(i),2).eq.2) then ! yield
c -----------------------------------------------------------------
         do j=1,move(i,nu_mv+1)
           if(move(i,j).eq.1) then
             if(green(i,j).gt.0)  then
              call adjust_saturation(i,MFRtmp,t,1)
	        exit
	       endif
           endif
         end do
!    determine the average flow on the major approaches

         do ik = 1, SignCount
           if(idnod(i).eq.SignData(ik)%node) then
             IndSig = ik
	       exit
	     endif
	   enddo

         IMajor=.False.
	   do iMM = 1, SignData(IndSig)%NofMajor
	     if(i.eq.SignApprh(IndSig)%major(iMM)) then ! link i is the major appraoch
             IMajor=.True.
	       exit
           endif
         enddo

         if(IMajor) then !link i is major approach
           do j=1,llink(i,nu_mv+1)
              capacity(i,j)=(green(i,j)*MFRtmp)
              tmp=green(i,j)*MFRtmp-ifix(capacity(i,j))
              if(tmp.gt.0.0001) then
                call random_number(r5)
                if(r5.le.tmp) capacity(i,j)=ifix(capacity(i,j))+1
              endif
           enddo


         else !link i is minor approach
	   
	   
	   

! Count averate flow rate on major approaches	   
	   TotMJflow = 0.0
! 	   do iip = 1, SignData(IndSig)%NofMinor
 	   do iip = 1, SignData(IndSig)%NofMajor
!	   	     LLT = SignApprh(IndSig)%minor(iip)
	   	     LLT = SignApprh(IndSig)%major(iip)
           TotMJflow=TotMJflow+aveoutflow(LLT)*3600/nlanes(LLT)
	   enddo
!         AvgMJflow = TotMJflow/SignData(IndSig)%NofMinor
         AvgMJflow = TotMJflow/SignData(IndSig)%NofMajor
         do ih = 1, level2N
           if(AvgMJflow.lt.YieldCapIND(ih)) then
	       IndCap = ih
	       exit
	     endif
	   enddo


		captot(i)= 0
	    capacity(i,:) = 0
		
		      
       do j=1,llink(i,nu_mv+1)
c -- Alex-adjustment to acount for dummy links:	  
c       if(idnod(llink(i,j)).gt.noofnodes_org) green(i,j)=tii*60	   
	   
         if(move(i,j).eq.1) then  ! Left turn movement
!           capacity(i,j)=
!     *     (green(i,j)*nlanes(i)*YieldCap(IndCap,1)/3600.0)
!             tmp=green(i,j)*nlanes(i)*YieldCap(IndCap,1)/3600.0-
!     *       ifix(capacity(i,j))
!             if(tmp.gt.0.0001) then
!               call random_number(r5)
!               if(r5.le.tmp) capacity(i,j)=ifix(capacity(i,j))+1
!             endif


! We use left_capacity() for left turn movement

           left_capacity(i)=
     *     (green(i,j)*nlanes(i)*YieldCap(IndCap,1)/3600.0)
             tmp=green(i,j)*nlanes(i)*YieldCap(IndCap,1)/3600.0-
     *       ifix(left_capacity(i))
             if(tmp.gt.0.0001) then
               call random_number(r5)
           if(r5.le.tmp) left_capacity(i)=ifix(left_capacity(i))+1
             endif


!*******************for dyna 930.7************************************************		 
	elseif(move(i,j).eq.3) then !right turn
            right_capacity(i)=
     *      (green(i,j)*nlanes(i)*
     *           YieldCap(min(4,total_count(i)+1),3)/3600.0)
            tmp=green(i,j)*nlanes(i)*
     *           YieldCap(min(4,total_count(i)+1),3)/3600.0
     *          -ifix(right_capacity(i))
            if(tmp.gt.0.0001) then
             call random_number(r5)
             if(r5.le.tmp) right_capacity(i)=ifix(right_capacity(i))+1
            endif 


	elseif(move(i,j).eq.2) then !through turn
      capacity(i,j)=
     *      (green(i,j)*nlanes(i)*
     *      (YieldCap(min(4,total_count(i)+1),2))/3600.0)
            tmp=green(i,j)*nlanes(i)*
     *      (YieldCap(min(4,total_count(i)+1),2))/3600.0
     *          -ifix(capacity(i,j))
            if(tmp.gt.0.0001) then
             call random_number(r5)
             if(r5.le.tmp) capacity(i,j)=ifix(capacity(i,j))+1
            endif

          else ! take average value of left and right for movements other1 and other 2
            capacity(i,j)=
     *      (green(i,j)*nlanes(i)*
     *      (YieldCap(min(4,total_count(i)+1),1)+
     *       YieldCap(min(4,total_count(i)+1),3))/2.0/3600.0)
            tmp=green(i,j)*nlanes(i)*
     *      (YieldCap(min(4,total_count(i)+1),1)+
     *       YieldCap(min(4,total_count(i)+1),3))/2.0/3600.0
     *          -ifix(capacity(i,j))
            if(tmp.gt.0.0001) then
             call random_number(r5)
             if(r5.le.tmp) capacity(i,j)=ifix(capacity(i,j))+1
            endif
          endif
!******************************End of addition*************************************




!         else ! take average value of through and right for movements other than left
!               capacity(i,j)=(green(i,j)*nlanes(i)*
!     *         (YieldCap(IndCap,2)+YieldCap(IndCap,3))/2.0/3600.0)
!               tmp=green(i,j)*nlanes(i)*(YieldCap(IndCap,2)+
!     *             YieldCap(IndCap,2))/2.0/3600.0 -ifix(capacity(i,j))
!!               if(tmp.gt.0.0001) then
 !                call random_number(r5)
 !                if(r5.le.tmp) capacity(i,j)=ifix(capacity(i,j))+1
 !              endif
 !        endif
!************************************end of deletion*********************************



	  captot(i)=max(captot(i),capacity(i,j),left_capacity(i),
     *	right_capacity(i))

         enddo
         endif !.not.IMajor


	endif ! control types
c --



!     do i = 1, SignCount
!        read(44,*) SignData(i)%node, SignData(i)%NofMajor, SignData(i)%NofMinor
!        read(44,*) (TmpMJAph(j),j=1,2*SignData(i)%NofMajor) 
!	    do k = 1, SignData(i)%NofMajor !get link number for major approach
!	     SignApprh(i)%major(k) = GetFLinkFromNode(idnum(TmpMJAph(k*2-1)),idnum(TmpMJAph(k*2)))
!	    enddo
!	    read(44,*) (TmpMnAph(j),j=1,2*SignData(i)%NofMinor)
!	    do k = 1, SignData(i)%NofMinor ! get link number for minor approach
!	      SignApprh(i)%minor(k) = GetFLinkFromNode(idnum(TmpMnAph(k*2-1)),idnum(TmpMnAph(k*2)))
!	    enddo
!      enddo



        endif !link_iden(i).lt.99
10    continue                 
c --
c --


      do i=1,noofarcs

	 if(link_iden(i).eq.100) then ! only for origin connectors
		captot(i) = tii*MaxFlowRate(i)
	  do j=1,llink(i,nu_mv+1)
          capacity(i,j) = tii*MaxFlowRate(i)
        end do
	 endif
	enddo

c	print *,right_capacity(111),iunod(111),idnod(111)
c     do j=1,llink(111,nu_mv+1)
c           print *, green(111,j)
c     enddo
c	pause

      return
      end 
