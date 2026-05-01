      subroutine somarginal
c  --
c  -- this subroutine is for calculating the marginals for SO algorithm
c  -- For details of the algorithm, please see the project report.

      use muc_mod
c  -- 
      real,allocatable::Marginal(:,:,:),TimePenal(:,:,:)
      real,allocatable::xp(:,:,:),TimePenal_Temp(:,:,:)
      real,allocatable::slopess(:,:),slopell(:,:)
      real,allocatable::slopels(:,:),slopesl(:,:)

      real::alpha = 0.50
      real::beta = 0.50

      logical Done 
      integer a,t,ts

      allocate(Marginal(noofarcs,aggint,2))
      allocate(TimePenal(noofarcs,aggint,2))
      
      allocate(slopess(noofarcs,aggint))
      allocate(slopell(noofarcs,aggint))
      allocate(slopels(noofarcs,aggint))
      allocate(slopesl(noofarcs,aggint))

      allocate(xp(noofarcs,aggint,2))
      allocate(TimePenal_Temp(noofarcs,aggint,nu_mv))
     		
      uplimit=99.99

c  -- xp is exactly as moveturnMG, number of vehicles ready to make left and other turns
c  -- this conversion is for shortening the naming
      xp(:,:,:) = moveturnMG(:,:,:)


	slopess(:,:) = 0
	slopell(:,:) = 0
	slopels(:,:) = 0
	slopesl(:,:) = 0
! End


      PenaltyMg(:,:,:)=0     
      do t = 1,aggint
         do a = 1,noofarcs
	      ip1=0
	      ip2=0
            p1=0.0
            p2=0.0
            do l = 1,nu_mv

!	write(122,*), 'openaltyMG(', a, t, l, ')=', openaltyMG(a,t,l)

              TimePenal_Temp(a,t,l) = TravelTime(a,t)+openaltyMG(a,t,l)
              if(TimePenal_Temp(a,t,l).gt.0.001) then
                if(move(a,l).eq.1.or.move(a,l).eq.6) then
	             ip1=ip1+1
                   p1=p1+TimePenal_Temp(a,t,l)
                elseif
     *             (move(a,l).ne.1.and.move(a,l).ne.6) then
	             ip2=ip2+1
                   p2=p2+TimePenal_Temp(a,t,l) 
                endif
              endif
            end do
	           if(ip1.gt.0) TimePenal(a,t,1) = p1/ip1
                 if(ip2.gt.0) TimePenal(a,t,2) = p2/ip2
         end do
      end do
     
c -----------------------------------------------
c  -- Start derivative calculation
c -----------------------------------------------
      do ts = 2, aggint-1
         do a = 1,noofarcs
                  xl1 = xp(a,ts-1,1)
                  xl2 = xp(a,ts,1)
                  xl3 = xp(a,ts+1,1)
                  xs1 = xp(a,ts-1,2)
                  xs2 = xp(a,ts,2)
                  xs3 = xp(a,ts+1,2)
                  tl1 = TimePenal(a,ts-1,1)
                  tl2 = TimePenal(a,ts,1)
                  tl3 = TimePenal(a,ts+1,1)
                  ts1 = TimePenal(a,ts-1,2)
                  ts2 = TimePenal(a,ts,2)
                  ts3 = TimePenal(a,ts+1,2)
                 dxlt = xl2-xl1
                dxlt1 = xl3-xl2
                 dxst = xs2-xs1
                dxst1 = xs3-xs2
                 dtlt = tl2-tl1
                dtlt1 = tl3-tl2
                 dtst = ts2-ts1
                dtst1 = ts3-ts2
c --  two sets of the linear equations are solved for the derivative of the
c --  movement with respect to the left and other movements
c --  The two sets of linear equations are:
c --  set one - solve for the derivatives of straight-move vehicles 
c --            contributed to left (dl/ds) and other movement (ds/ds)
c --    dxlt (ds/dl) + dxst (ds/ds) = dtst
c --    dxlt1(ds/dl) + dxst1(ds/ds) = dtst1

c --  set two - solve for the derivatives of left-turn vehicles 
c --            contributed to left (dl/dl) and other movement (ds/dl)
c --    dxlt (dl/dl) + dxst (dl/ds) = dtlt
c --    dxlt1(dl/dl) + dxst1(dl/ds) = dtlt1

                    d = dxlt*dxst1-dxst*dxlt1 ! determinant 
                  dl1 = dtlt*dxst1-dxst*dtlt1
                  dl2 = dxlt*dtlt1-dtlt*dxlt1
                  ds1 = dtst*dxst1-dxst*dtst1
                  ds2 = dxlt*dtst1-dtst*dxlt1

!	write(140,*), 'ts=', ts, 'a=', a

!	write(140,*), 'before...'
!	write(140,*), 'slopess(', a, ts, ')=', slopess(a,ts)
!	write(140,*), 'slopesl(', a, ts, ')=', slopesl(a,ts)
!	write(140,*), 'slopell(', a, ts, ')=', slopell(a,ts)
!	write(140,*), 'slopels(', a, ts, ')=', slopels(a,ts)

!	write(140,*), 'determinant=', d

	if(ts.gt.1) then
	  slopess(a,ts) = slopess(a,ts-1)
	  slopesl(a,ts) = slopesl(a,ts-1)
	  slopell(a,ts) = slopell(a,ts-1)
	  slopels(a,ts) = slopels(a,ts-1)
	endif
      
	if (d.ne.0.0) then ! co-linearity in the system equations
!       if(slopess(a,ts).gt.0) slopess(a,ts) = min(100.0,ds2/d) !# of other-turned veh contributed to travel time for other-turns
!       if(slopesl(a,ts).gt.0) slopesl(a,ts) = min(100.0,ds1/d) !# of other-turned veh contributed to travel time for left-turn                
!	  if(slopell(a,ts).gt.0) slopell(a,ts) = min(100.0,dl1/d) !# of left-turned veh contributed to travel time for left-turn          
!	  if(slopels(a,ts).gt.0) slopels(a,ts) = min(100.0,dl2/d) !# of left-turned veh contributed to travel time for other turns	     
		 
	  if(slopess(a,ts) .ge. 0.0) then
	    slopess(a,ts) = min(100.0,ds2/d) !# of other-turned veh contributed to travel time for other-turns
	  endif		 
	  
	  if(slopesl(a,ts) .ge. 0.0) then
		slopesl(a,ts) = min(100.0,ds1/d) !# of other-turned veh contributed to travel time for left-turn                
	  endif
	  
	  if(slopell(a,ts) .ge. 0.0) then
	    slopell(a,ts) = min(100.0,dl1/d) !# of left-turned veh contributed to travel time for left-turn          
	  endif
	  
	  if(slopels(a,ts) .ge. 0.0) then
	    slopels(a,ts) = min(100.0,dl2/d) !# of left-turned veh contributed to travel time for other turns	     
	  endif
			 	
!	write(140,*), 'if (d.ne.0.0)'
!	write(140,*), 'slopess(', a, ts, ')=', slopess(a,ts)
!	write(140,*), 'slopesl(', a, ts, ')=', slopesl(a,ts)
!	write(140,*), 'slopell(', a, ts, ')=', slopell(a,ts)
!	write(140,*), 'slopels(', a, ts, ')=', slopels(a,ts)
!	write(140,*), 'end of if (d.ne.0.0)'

	endif

c --   examine these four derivatives individually if co-linearity or negative
c --   slopell
!       if(d.eq.0.0.or.slopell(a,ts).lt.0.0) then
!         Done = .False.
!	   if(.not.Done) then 
!            do k = 1,aggint-ts
!               if ((xp(a,ts+k,1)-xp(a,ts,1)) .ne. 0.0) then
!                 slopell(a,ts) = (TimePenal(a,ts+k,1)-TimePenal(a,ts,1))
!     *                           /(xp(a,ts+k,1)-xp(a,ts,1))
!                  if (slopell(a,ts) .gt. 0.0) then
!				   Done = .True.
!	               exit
!	            endif
!               endif
!            enddo
!	   endif
!
!	   if(.not.Done) then 
!            do k = 1,ts-1
!               if ((xp(a,ts-k,1)-xp(a,ts,1)) .ne. 0.0) then
!                 slopell(a,ts) = (TimePenal(a,ts-k,1)-TimePenal(a,ts,1))
!     *                           /(xp(a,ts-k,1)-xp(a,ts,1))
!                  if (slopell(a,ts) .gt. 0.0) then
!				 Done = .True.
!	             exit
!	            endif
!               endif
!            enddo   
!         endif
!	   if(.not.Done)  slopell(a,ts) = 0.0

!	 write(140,*), 'slopell(', a, ts, ')=', slopell(a,ts)	

!       endif



c --   slopess
!       if(d.eq.0.0.or.slopess(a,ts).lt.0.0) then
!         Done = .False.
!	   if(.not.Done) then 
!         do k = 1,aggint-ts
!               if ((xp(a,ts+k,2)-xp(a,ts,2)) .ne. 0.0) then
!                 slopess(a,ts) = (TimePenal(a,ts+k,2)-TimePenal(a,ts,2))
!     *                           /(xp(a,ts+k,2)-xp(a,ts,2))
!                  if (slopess(a,ts) .gt. 0.0) then
!				   Done = .True.
!	               exit
!	            endif
!               endif
!	   enddo
!	   endif

!	   if(.not.Done) then 
!         do k = 1,ts-1
!               if ((xp(a,ts-k,2)-xp(a,ts,2)) .ne. 0.0) then
!                 slopess(a,ts) = (TimePenal(a,ts-k,2)-TimePenal(a,ts,2))
!     *                           /(xp(a,ts-k,2)-xp(a,ts,2))
!                  if (slopess(a,ts) .gt. 0.0) then
!				   Done = .True.
!	               exit
!	            endif
!               endif
!         enddo
!         endif
!	   if(.not.done)  slopess(a,ts) = 0.0

!	 write(140,*), 'slopess(', a, ts, ')=', slopess(a,ts)	

!	 endif


c --   slopesl
!       if(d.eq.0.0.or.slopesl(a,ts).lt.0.0) then
!         Done = .False.
!	   if(.not.Done) then 
!            Do k=1,aggint-ts
!               if ((xp(a,ts+k,1)-xp(a,ts,1)) .ne. 0.0) then
!              slopesl(a,ts)=(TimePenal(a,ts+k,2)-TimePenal(a,ts,2))/
!     *                         (xp(a,ts+k,1)-xp(a,ts,1))
!                 if (slopesl(a,ts) .gt. 0.0) then
!			      Done = .True.
!	              exit
!	           endif
!               endif
!            enddo
!	   endif

!	   if(.not.Done) then 
!            Do k=1,ts-1
!               if ((xp(a,ts-k,1)-xp(a,ts,1)) .ne. 0.0) then
!              slopesl(a,ts)=(TimePenal(a,ts-k,2)-TimePenal(a,ts,2))/
!     *                         (xp(a,ts-k,1)-xp(a,ts,1))
!                  if (slopesl(a,ts) .gt. 0.0) then
!				   Done = .True.
!	               exit
!	            endif
!               endif
!            enddo
!          endif
!	   if(.not.done)  slopesl(a,ts) = 0.0

!	 write(140,*), 'slopesl(', a, ts, ')=', slopesl(a,ts)

!       endif


c --   slopels
!       if(d.eq.0.0.or.slopels(a,ts).lt.0.0) then
!         Done = .False.
!	   if(.not.Done) then 
!           Do k=1,aggint-ts
!               if ((xp(a,ts+k,2)-xp(a,ts,2)) .ne. 0.0) then
!              slopels(a,ts)=(TimePenal(a,ts+k,1)-TimePenal(a,ts,1))/
!     *                         (xp(a,ts+k,2)-xp(a,ts,2))
!                  if (slopels(a,ts) .gt. 0.0) then
!				  Done = .True.
!	              exit
!	            endif
!               endif
!           enddo
!	   endif

!	   if(.not.Done) then 
!            Do k=1,ts-1
!               if ((xp(a,ts-k,2)-xp(a,ts,2)) .ne. 0.0) then
!              slopels(a,ts)=(TimePenal(a,ts-k,1)-TimePenal(a,ts,1))/
!     *                         (xp(a,ts-k,2)-xp(a,ts,2))
!                  if (slopels(a,ts) .gt. 0.0) then
!				   Done = .True.
!	               exit
!	            endif
!               endif
!            enddo   
!          endif
!	   if(.not.done)  slopels(a,ts) = 0.0

!	 write(140,*), 'slopels(', a, ts, ')=', slopels(a,ts)

!       endif
      
	
      enddo
	enddo

c --   construct the final marginals
c --   The following part only constitue the marginals 
c --   The travel time and penalty part will be added in kspso_main
       do t=1,aggint
          do a=1,noofarcs
           Marginal(a,t,1)=slopell(a,t)*xp(a,t,1)+
     *         slopesl(a,t)*xp(a,t,2)*alpha+slopesl(a,t)*DiffMG(a,t)

           Marginal(a,t,2)=slopess(a,t)*xp(a,t,2)+
     *         slopels(a,t)*xp(a,t,1)*beta+slopels(a,t)*DiffMG(a,t)    
          end do
      end do
c ------------------------------------------------------------------
c  -- convert to the form needed by the Least-Cost Path Algorithm
c ------------------------------------------------------------------
      do 300 t = 1, aggint
      do 300 i=1,noofarcs
         nodeup=iunod(i)
         ip=ForToBackLink(i)
         do 301 j=1,movein(i,nu_mv+1)
          il=inlink(i,j)
          itmp=iunod(il)
          mtmp=backpointr(nodeup+1)-backpointr(nodeup)
          Lflag = 0
          do 302 kk=1,mtmp
           itmp2=UNodeOfBackLink((kk-1)+backpointr(nodeup))
           if(itmp.eq.itmp2) then
              Lflag = 1
             if(movein(i,j).eq.6.or.movein(i,j).eq.1) then
		      penaltyMG(t,ip,kk)=Marginal(il,t,1) 
             else
                penaltyMG(t,ip,kk)=Marginal(il,t,2)
	       endif
             if(penaltyMG(t,ip,kk).gt.99.999) then
		      penaltyMG(t,ip,kk)=99.999 
             elseif(penaltyMG(t,ip,kk).lt.0) then
		      penaltyMG(t,ip,kk)=0
             endif

!	write(123,*), 'penaltyMG(', t, ip, kk, ')=', penaltyMG(t,ip,kk)

             go to 301

           endif
302   continue
           if(Lflag.eq.0) write(*,*) 'somargin match error'
301   continue
300   continue
c ----------------------------------------------------------

      deallocate(Marginal)
      deallocate(TimePenal)
      deallocate(xp)
      deallocate(slopess)
      deallocate(slopell)
      deallocate(slopels)
      deallocate(slopesl)
      deallocate(TimePenal_Temp)

     
      return
      end

!-------------------------------------------------------------------------------
!-------------------------------------------------------------------------------


	subroutine somarginal_siminterval

c	This subroutine is for calculating the marginals for SO algorithm
c     It calculates the so marginals for each simulation interval,
c     and aggragates them for each aggragation interval
c  -- For details of the algorithm, please see the project report.

      use muc_mod
c  -- 
      real,allocatable::Marginal(:,:,:),TimePenal(:,:,:)
      real,allocatable::xp(:,:,:),TimePenal_Temp(:,:,:)
      real,allocatable::slopess(:,:),slopell(:,:)
      real,allocatable::slopels(:,:),slopesl(:,:)
	real,allocatable::Marginal_tmp(:,:)

      real::alpha = 0.50
      real::beta = 0.50

	logical Done 
      integer a,t,ts
      integer aggcount

	integer icentroid, iupstreamnode


!      allocate(Marginal(noofarcs,aggint,2))
!      allocate(TimePenal(noofarcs,aggint,2))
      
!      allocate(slopess(noofarcs,aggint))
!      allocate(slopell(noofarcs,aggint))
!      allocate(slopels(noofarcs,aggint))
!      allocate(slopesl(noofarcs,aggint))

!      allocate(xp(noofarcs,aggint,2))
!      allocate(TimePenal_Temp(noofarcs,aggint,nu_mv))



      allocate(Marginal(noofarcs,aggint,2))
	allocate(Marginal_tmp(noofarcs,2))
      allocate(TimePenal(noofarcs,numof_siminterval,2))
      allocate(xp(noofarcs,numof_siminterval,2))
      allocate(TimePenal_Temp(noofarcs,numof_siminterval,nu_mv))
	allocate(slopess(noofarcs,numof_siminterval))
      allocate(slopell(noofarcs,numof_siminterval))
      allocate(slopels(noofarcs,numof_siminterval))
      allocate(slopesl(noofarcs,numof_siminterval))

! End
     		
      uplimit=99.99

c  -- xp is exactly as moveturnMG_sim, number of vehicles ready to make left and other turns
c  -- this conversion is for shortening the naming
      xp(:,:,:) = moveturnMG_sim(:,:,:)


	slopess(:,:) = 0
	slopell(:,:) = 0
	slopels(:,:) = 0
	slopesl(:,:) = 0

	Marginal_tmp(:,:) = 0
	Marginal(:,:,:) = 0
! End

      PenaltyMg(:,:,:)=0   ! for final so marginal used in the TDKSP  

! Initialize openaltyMG_sim from any connector to outbound links as infinity
      do ilink = 1, noofarcs
	if(link_iden(ilink).eq.100) then ! connector 

	do iaa=1,llink(ilink,nu_mv+1) ! for each outbound link of connector
	
	imovement = iaa

      openaltyMG_sim(ilink,:,imovement)= infinity
	
	enddo

	endif

	enddo


! Put entry queue time as openaltyMG_sim from a connector to outbound generation links
	  	
      do iz=1,nzones
      do il=1,NoofGenLinksPerZone(iz)
	igenelink = LinkNoInZone(iz,il)

	icentroid = origin(iz) ! Centroid node ID for origin zone iz
	iupstreamnode = iunod(igenelink) ! Upstream node ID for generation link igenelink
									 ! Find the connector	
	iconnector = GetFLinkFromNode(icentroid,iupstreamnode)
	imovement = -1

	do iaa=1,llink(iconnector,nu_mv+1) ! for each outbound link of connector
	if(llink(iconnector,iaa).eq.igenelink) then
	imovement = iaa
	endif
	enddo	
      
	if(imovement.eq.  -1) then
	write(*,*) "cannot find corresponding movement from a connector
     + to current generation link"
	stop
	endif


      openaltyMG_sim(iconnector,:,imovement)= 
     +PenaltyEntry_sim(igenelink,:)
      
	enddo
	enddo
	



!      do t = 1,aggint
       do t = 1,numof_siminterval
         do a = 1,noofarcs
	      ip1=0
	      ip2=0
            p1=0.0
            p2=0.0
            do l = 1,nu_mv

!	write(122,*), 'openaltyMG(', a, t, l, ')=', openaltyMG(a,t,l)


!              TimePenal_Temp(a,t,l) = TravelTime(a,t)+openaltyMG(a,t,l)
              TimePenal_Temp(a,t,l) = TravelTime_sim(a,t) + 
     +                                openaltyMG_sim(a,t,l)
! End

              if(TimePenal_Temp(a,t,l).gt.0.001) then
                if(move(a,l).eq.1.or.move(a,l).eq.6) then
	             ip1=ip1+1
                   p1=p1+TimePenal_Temp(a,t,l)
                elseif
     *             (move(a,l).ne.1.and.move(a,l).ne.6) then
	             ip2=ip2+1
                   p2=p2+TimePenal_Temp(a,t,l) 
                endif
              endif
            end do
	           if(ip1.gt.0) TimePenal(a,t,1) = p1/ip1
                 if(ip2.gt.0) TimePenal(a,t,2) = p2/ip2
         end do
      end do
     
c -----------------------------------------------
c  -- Start derivative calculation
c -----------------------------------------------


!      do ts = 2, aggint-1
       do ts = 2, numof_siminterval-1
! End
         do a = 1,noofarcs
                  xl1 = xp(a,ts-1,1)
                  xl2 = xp(a,ts,1)
                  xl3 = xp(a,ts+1,1)
                  xs1 = xp(a,ts-1,2)
                  xs2 = xp(a,ts,2)
                  xs3 = xp(a,ts+1,2)
                  tl1 = TimePenal(a,ts-1,1)
                  tl2 = TimePenal(a,ts,1)
                  tl3 = TimePenal(a,ts+1,1)
                  ts1 = TimePenal(a,ts-1,2)
                  ts2 = TimePenal(a,ts,2)
                  ts3 = TimePenal(a,ts+1,2)
                 dxlt = xl2-xl1
                dxlt1 = xl3-xl2
                 dxst = xs2-xs1
                dxst1 = xs3-xs2
                 dtlt = tl2-tl1
                dtlt1 = tl3-tl2
                 dtst = ts2-ts1
                dtst1 = ts3-ts2
c --  two sets of the linear equations are solved for the derivative of the
c --  movement with respect to the left and other movements
c --  The two sets of linear equations are:
c --  set one - solve for the derivatives of straight-move vehicles 
c --            contributed to left (dl/ds) and other movement (ds/ds)
c --    dxlt (ds/dl) + dxst (ds/ds) = dtst
c --    dxlt1(ds/dl) + dxst1(ds/ds) = dtst1

c --  set two - solve for the derivatives of left-turn vehicles 
c --            contributed to left (dl/dl) and other movement (ds/dl)
c --    dxlt (dl/dl) + dxst (dl/ds) = dtlt
c --    dxlt1(dl/dl) + dxst1(dl/ds) = dtlt1

                    d = dxlt*dxst1-dxst*dxlt1 ! determinant 
                  dl1 = dtlt*dxst1-dxst*dtlt1
                  dl2 = dxlt*dtlt1-dtlt*dxlt1
                  ds1 = dtst*dxst1-dxst*dtst1
                  ds2 = dxlt*dtst1-dtst*dxlt1

!	write(140,*), 'ts=', ts, 'a=', a

!	write(140,*), 'before...'
!	write(140,*), 'slopess(', a, ts, ')=', slopess(a,ts)
!	write(140,*), 'slopesl(', a, ts, ')=', slopesl(a,ts)
!	write(140,*), 'slopell(', a, ts, ')=', slopell(a,ts)
!	write(140,*), 'slopels(', a, ts, ')=', slopels(a,ts)

!	write(140,*), 'determinant=', d

	if(ts.gt.1) then
	  slopess(a,ts) = slopess(a,ts-1)
	  slopesl(a,ts) = slopesl(a,ts-1)
	  slopell(a,ts) = slopell(a,ts-1)
	  slopels(a,ts) = slopels(a,ts-1)
	endif
      
	if (d.ne.0.0) then ! co-linearity in the system equations
!       if(slopess(a,ts).gt.0) slopess(a,ts) = min(100.0,ds2/d) !# of other-turned veh contributed to travel time for other-turns
!       if(slopesl(a,ts).gt.0) slopesl(a,ts) = min(100.0,ds1/d) !# of other-turned veh contributed to travel time for left-turn                
!	  if(slopell(a,ts).gt.0) slopell(a,ts) = min(100.0,dl1/d) !# of left-turned veh contributed to travel time for left-turn          
!	  if(slopels(a,ts).gt.0) slopels(a,ts) = min(100.0,dl2/d) !# of left-turned veh contributed to travel time for other turns	     
		 
	  if(slopess(a,ts) .ge. 0.0) then
	    slopess(a,ts) = min(100.0,ds2/d) !# of other-turned veh contributed to travel time for other-turns
	  endif		 
	  
	  if(slopesl(a,ts) .ge. 0.0) then
		slopesl(a,ts) = min(100.0,ds1/d) !# of other-turned veh contributed to travel time for left-turn                
	  endif
	  
	  if(slopell(a,ts) .ge. 0.0) then
	    slopell(a,ts) = min(100.0,dl1/d) !# of left-turned veh contributed to travel time for left-turn          
	  endif
	  
	  if(slopels(a,ts) .ge. 0.0) then
	    slopels(a,ts) = min(100.0,dl2/d) !# of left-turned veh contributed to travel time for other turns	     
	  endif
			 	
!	write(140,*), 'if (d.ne.0.0)'
!	write(140,*), 'slopess(', a, ts, ')=', slopess(a,ts)
!	write(140,*), 'slopesl(', a, ts, ')=', slopesl(a,ts)
!	write(140,*), 'slopell(', a, ts, ')=', slopell(a,ts)
!	write(140,*), 'slopels(', a, ts, ')=', slopels(a,ts)
!	write(140,*), 'end of if (d.ne.0.0)'

	endif      
	
      enddo
	enddo


c --   construct the final marginals
c --   The following part only constitue the marginals 
c --   The travel time and penalty part will be added in kspso_main
!       do t=1,aggint
!          do a=1,noofarcs
!           Marginal(a,t,1)=slopell(a,t)*xp(a,t,1)+
!     *         slopesl(a,t)*xp(a,t,2)*alpha+slopesl(a,t)*DiffMG(a,t)
!
!           Marginal(a,t,2)=slopess(a,t)*xp(a,t,2)+
!     *         slopels(a,t)*xp(a,t,1)*beta+slopels(a,t)*DiffMG(a,t)    
!          end do
!      end do
       
! aggregate the so marginals from simulation intervals to aggregation intervals
	do t=1,numof_siminterval
        do a=1,noofarcs
           Marginal_tmp(a,1)=Marginal_tmp(a,1) + slopell(a,t)*xp(a,t,1)+
     *         slopesl(a,t)*xp(a,t,2)*alpha+slopesl(a,t)*DiffMG_sim(a,t)

           Marginal_tmp(a,2)=Marginal_tmp(a,2) + slopess(a,t)*xp(a,t,2)+
     *         slopels(a,t)*xp(a,t,1)*beta+slopels(a,t)*DiffMG_sim(a,t)
     
           if(MOD(t, ftr).eq.0)then
             aggcount = t/ftr
	       Marginal(a,aggcount,1) = max(0.0, Marginal_tmp(a,1))/ftr
             Marginal(a,aggcount,2) = max(0.0, Marginal_tmp(a,2))/ftr

	       Marginal_tmp(a,1) = 0
	       Marginal_tmp(a,2) = 0
	     endif
         
        end do
      end do

! End


c ------------------------------------------------------------------
c  -- convert to the form needed by the Least-Cost Path Algorithm
c ------------------------------------------------------------------
      do 300 t = 1, aggint
      do 300 i=1,noofarcs
         nodeup=iunod(i)
         ip=ForToBackLink(i)
         do 301 j=1,movein(i,nu_mv+1)
          il=inlink(i,j)
          itmp=iunod(il)
          mtmp=backpointr(nodeup+1)-backpointr(nodeup)
          Lflag = 0
          do 302 kk=1,mtmp
           itmp2=UNodeOfBackLink((kk-1)+backpointr(nodeup))
           if(itmp.eq.itmp2) then
              Lflag = 1
             if(movein(i,j).eq.6.or.movein(i,j).eq.1) then
		      penaltyMG(t,ip,kk)=Marginal(il,t,1) 
             else
                penaltyMG(t,ip,kk)=Marginal(il,t,2)
	       endif
             if(penaltyMG(t,ip,kk).gt.99.999) then
		      penaltyMG(t,ip,kk)=99.999 
             elseif(penaltyMG(t,ip,kk).lt.0) then
		      penaltyMG(t,ip,kk)=0
             endif

!	write(123,*), 'penaltyMG(', t, ip, kk, ')=', penaltyMG(t,ip,kk)

             go to 301

           endif
302   continue
           if(Lflag.eq.0) write(*,*) 'somargin match error'
301   continue
300   continue
c ----------------------------------------------------------

      deallocate(Marginal)
      deallocate(TimePenal)
      deallocate(xp)
      deallocate(slopess)
      deallocate(slopell)
      deallocate(slopels)
      deallocate(slopesl)
      deallocate(TimePenal_Temp)
	deallocate(Marginal_tmp)

      return

	end


