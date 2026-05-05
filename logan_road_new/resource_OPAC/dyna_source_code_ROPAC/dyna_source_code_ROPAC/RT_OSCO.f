      subroutine RT_OSCO(Nosco,n1,n2,t_now,nu_ph2,narcs,iphaseRT,
     + nodenumber,lll)
c	  Kqueue,matrixgreen,mgreen,
c     +	,nsign,noofnodes,nu_mv,tii,contveh_que)
	 
c --  max = maximum green (in 6 seconds intervals)
c --  mim = minimum green (in 6 seconds intervals)
c -- 	nf =   number of phases
c --  Nosco = number of invervals (T/delta) = Nosco
      use muc_mod

      integer error,Y,i,nf,j,g,pp1,l,Kosco,q,lll,m,o,w,a,wy,w1,b
      integer min1,max1,iphaseRT,cont,limit,salida,ik,nodenumber
      integer limit2,limit3,limit1,Y2,Y1,Y3,Y4,Y5,Y6,limitj,limitK
      integer limito,limitm,limitl,limit4,limit5,limit6,limit7,limitll	  
c      integer,allocatable::matrixvehicle2(:,:,:)
      integer w2,w3,d,w4,e,w5,f,w6,r,h,narcs,n1,n2,Nosco,nu_ph2,wyv
      integer first
c      integer Kqueue(narcs,7),noofnodes,nu_mv
c      integer matrixgreen(n2-n1+1,Nosco)
c      integer mgreen(n2-n1+1,Nosco),contveh_que(2,nu_ph2,narcs)
c      integer nsign(noofnodes*nu_mv,14)	 	  
      real t_now
c      real tii
c     integer Nosco, Y, w, z1, z2, z3, z4, z5, z6, z7, max, min, nf
C      print *,'Alex241a',iphaseRT

c	open(unit=3,file='matrix_vehicle.dat',STATUS='UNKNOWN')
c	open(unit=4,file='matrix_verdes.dat',STATUS='UNKNOWN')
c	open(unit=6,file='matrix_carros.dat',STATUS='UNKNOWN')
      nf=n2-n1+1

c      print *,'Alexmatrixvehicle2',nf,Nosco,narcs
      allocate(matrixvehicle2(nf,Nosco+1,narcs),stat=error)
      if(error.ne.0) print *, 'error allocating matrixvehicle2'
      matrixvehicle2(:,:,:)=0
	  
      allocate(matrixvehicle1(nf,Nosco+1,narcs),stat=error)
      if(error.ne.0) print *, 'error allocating matrixvehicle1'
      matrixvehicle1(:,:,:)=0	

      allocate(matrixvehicle4(nf,Nosco+1),stat=error)
      if(error.ne.0) print *, 'error allocating matrixvehicle4'
      matrixvehicle4(:,:)=0	  
	  
      cont2=0
c	do i=1,nf
c	do j=1,Nosco
c	matrixvehicle(i,j)=0
c	enddo
c	enddo
c -- 
c -- define the critical link and its vehicle_queue.
c -- the critical link is the link with the maximum queue	during each phase.
c --
c -- phase is a varibale to keep track of the current phase number.
c --
c -- Note : the difference between n1, n2 and phase is the following
c -- n1 and n2 are calculated by sorting all the phases in the network.
c -- n1 and n2 define the starting and ending phases for the current node.
c -- The "phase" is just the phase number, provided in the control input
c -- file, at the current node ! "nsign(i,1)"
c --
C      print *,'Alex241',iphaseRT,nu_ph2
c      if(nodenumber.eq.5) print *,
c     +	  'before RT_GET_DELAY',n1,n2,Nosco,nf,narcs	
	 
      call RT_GET_DELAY(n1,n2,Nosco,nf,narcs,nodenumber)
c	  ,Kqueue,matrixvehicle2,contveh_que,
c     +	  nu_ph2)
c      print *,'after RT_GET_DELAY'		 
C      print *,'Alex242',iphaseRT
	  
       mindelay=9999999
c --
c	write(1,*) ik
c      print *,'Alex2420',iphaseRT
      ik=nsign(iphaseRT,1)
c	if (nsign(iphase,13).gt.t_now) then
c      print *,'Alex2421'
c -- bounds based on minimum and maximum green times
      if((t_now-nsign(iphaseRT,12)).ge.nsign(iphaseRT,3))then
       exttime=0
c      print *,'Alex2422'	   
c	 exttime=nint((nsign(iphase,13)-t_now)/(tii*60))
      else
c      print *,'Alex2423'	  
c      exttime=nint(aint((nsign(iphaseRT,3)-
c     +	(t_now-nsign(iphaseRT,12)))/(tii*60)))
      exttime=nint((nsign(iphaseRT,3)-
     +	  (t_now-nsign(iphaseRT,12)))/(tii*60))	 
      endif
c      print *,'Alex2424'	  
c      endtime=nint(aint((nsign(iphaseRT,2)-(t_now-nsign(iphaseRT,12)))/
c     +	  (tii*60))+1)
c -- based on maximum green time
      endtime=nint((nsign(iphaseRT,2)-
     +	  (t_now-nsign(iphaseRT,12)))/(tii*60))	 
c	else
c	exttime=ifix(nsign(iphase,3)/(tii*60))
c	endtime=ifix(nsign(iphase,2)/(tii*60))
c	endif
c      print *,'Alex242a'

      cont=0

c --  start loop for each phase

c      if(nodenumber.eq.5.and.lll*tii.ge.4) print *,'alex_15'
c     +	  ,n1,n2,nf,ik,iphaseRT

      do 15 w=1,nf
        wy=0
        z1=1
        Y=w
c        Y1=w	
c	Y=ik		
c	Y1=ik
        if(Y.gt.nf)then
            z1=-1
	        Y=Y-nf
        endif

c --  start phase 1
c	if((w.eq.ik).and.(Y.eq.1)) then
        if(w.eq.ik)then
          min1=exttime
          max1=endtime
        else
c          max1=nint(aint(nsign(iphaseRT,2)/(tii*60))+1)
c          min1=nint(aint(nsign(iphaseRT,3)/(tii*60)))
          max1=ifix(nsign(w+n1-1,2)/(tii*60))
          min1=ifix(nsign(w+n1-1,3)/(tii*60))
          if(min1.lt.1) min1=1

      wy=1  		  
      if(nsign(w+n1-1,3)-(t_now-nsign(w+n1-1,12)).gt.0)then	  
        if(nsign(w+n1-1,3)-(t_now-nsign(w+n1-1,12))+
     +   (nsign(w+n1-1,14)-nsign(w+n1-1,13)).lt.tii*60)then
c         wy=0
        endif
      else
        if((nsign(w+n1-1,14)-nsign(w+n1-1,13)).lt.tii*60)then
c         wy=0
        endif
      endif		  
							! this is to add lost for changing phase . . .
        endif

c	if (min.eq.0) then
c		    Y=Y+1
c		    if (Y.gt.nf) then
c			    Y=Y-nf
c		    endif
c			ch=1
c	else
c			 ch=0
c	endif

c      if(nodenumber.eq.5) print *,
c     +	  'Alex242b',min1,max1,wy,w,ik

      do 100 a=min1,max1
	      x=0
c	      do g=1,nf
c	         do h=1,Nosco
          matrixgreen(:,:)=0
c	         enddo
c		  enddo
         first=0
		 
c --  filling phase 1

c      print *,'Alex242b1',wy,a,Nosco,x
        if(Y.eq.ik)then
          wy=0
          min1=exttime
          max1=endtime
        else
          max1=ifix(nsign(Y+n1-1,2)/(tii*60))
          min1=ifix(nsign(Y+n1-1,3)/(tii*60))
      wy=1  
	  
      if(nsign(Y+n1-1,3)-(t_now-nsign(Y+n1-1,12)).gt.0)then	  
        if(nsign(Y+n1-1,3)-(t_now-nsign(Y+n1-1,12))+
     + (nsign(Y+n1-1,14)-nsign(Y+n1-1,13)).lt.tii*60)then
c       wy=0
       endif
      else
      if((nsign(Y+n1-1,14)-nsign(Y+n1-1,13)).lt.tii*60)then
c       wy=0
      endif
      endif		  
        endif

           do i=1+wy,a
             if(i.le.Nosco)then	
			       first=1
                   matrixgreen(Y,i)=1
             else
                   x=1
                   exit
             endif
           enddo
		   
c      if(nodenumber.eq.5.and.lll*tii.ge.4) 
c     +	  print *,'Alex242b3',wy,a,Nosco,x,i
	 
                   z2=1
				   
c           if((x.eq.1).or.(i-1.eq.Nosco).or.
c     + ((i-1.lt.Nosco).and.(i.eq.max1)))then
         salida=0
           if((x.eq.1).or.(i-1.eq.Nosco))then
	 
              cont=cont+1
c	         write(1,*) cont
c			 write(3,*) cont
c      print *,'Alex243',n1,n2,Nosco,nf,narcs 	 
      call RT_DELAY(n1,n2,Nosco,nf,narcs,nodenumber,lll)
c	  ,Kqueue,matrixgreen,mgreen,
c     + matrixvehicle2,
c     + nsign,noofnodes,nu_mv,SatFlowRate,tii) 
C      print *,'Alex244'
c		     write(1,10) ((matrixgreen(g,h), h=1, Nosco), g=1, nf)
c			 write(3,11) ((matrixvehicle(g,h), h=1, Nosco), g=1, nf)
                    do g=1,nf
						do pp1=1,Nosco
					    matrixgreen(g,pp1)=0				       
						enddo
                    enddo
			      goto 100
            endif
			  
c      print *,'Alex245'
         Y1=Y
          do 150 w1=1,nf
		     Y=Y+w1
		     if(Y.gt.nf)then
		        z2=-1
			    Y=Y-nf
		     endif
             if(Y.NE.Y1)then
c--  start phase 2

      if(first.eq.0.and.Y.eq.ik)then
        goto 150	
      else

C      do 200 b=nint(aint(nsign(Y+n1-1,3)/(tii*60))),
C     +	nint(aint(nsign(Y+n1-1,2)/(tii*60))+1)
               do g=1,nf
				    do pp1=i,Nosco
					    matrixgreen(g,pp1)=0
    				enddo
   			   enddo	

      do 200 b=nint(nsign(Y+n1-1,3)/(tii*60)),
     +	nint(nsign(Y+n1-1,2)/(tii*60))	 
	 
		     x=0

c--  filling phase 2

              do j=i+1,i+b
			    if(j.le.Nosco)then
				
c      print *,'Alex242b3',Y,j,i,b	
	               first=1
				   matrixgreen(Y,j)=1
                else
				   x=1
				   exit
                endif
              enddo
			  z3=1

      limit=nint(nsign(Y+n1-1,2)/(tii*60))
      limitj=nint(nsign(Y+n1-1,3)/(tii*60))		  
      limit2=max1+nint(nsign(Y+n1-1,2)/(tii*60))			  
			  
c      if(nodenumber.eq.5.and.lll*tii.ge.4) 
c     + print *,'Alex246',x,j,Nosco,limit
        salida=0
		
      if((x.eq.1).or.((j-1.eq.Nosco).and.(i.gt.max1)).or.
     + ((i.gt.max1).and.(j-2.ge.limit2).and.(b.eq.limit)
     + .and.(nf.le.2)).or.((i.ge.min1).and.(j-i.ge.limitj)
     + .and.(nf.le.2)))then
	 
C -- 

c      if(nodenumber.eq.5.and.lll*tii.ge.4) print *,'alex_2'	 
	 
c        if((x.eq.1).or.(j-1.eq.Nosco))then	 
	 
			  	 cont=cont+1
c	             write(1,*) cont
c				 write(3,*) cont
C      print *,'Alex245'	
c      print *,'before RT_DELAY',n1,n2,Nosco,nf,narcs 	
      call RT_DELAY(n1,n2,Nosco,nf,narcs,nodenumber,lll)
c	  ,Kqueue,matrixgreen,mgreen,
c     + matrixvehicle2,
c     + nsign,noofnodes,nu_mv,SatFlowRate,tii) 
c      print *,'after RT_DELAY'		 
C      print *,'Alex246'
c		         write(1,10) ((matrixgreen(g,h), h=1, Nosco), g=1, nf)
c			 write(3,11) ((matrixvehicle(g,h), h=1, Nosco), g=1, nf)
         goto 200
       salida=1
         endif	
		 
c               do g=1,nf
c				    do pp1=i+1,Nosco
c					    matrixgreen(g,pp1)=0
c    				enddo
c   			   enddo	
			   
c       if(salida.eq.1) exit
	   
         Y2=Y
         do 250 w2=1,nf	  
              Y=Y+w2
              if(Y.gt.nf)then
                 z3=-1
                 Y=Y-nf
              endif
            if(Y2.NE.Y)then
			
               if(nf.ge.3)then

c--  start phase 3
c      if(nodenumber.eq.5.and.lll*tii.ge.4) 
c     + print *,'Alex2470',nint(nsign(Y+n1-1,3)/(tii*60)),
c     +		nint(aint(nsign(Y+n1-1,2)/(tii*60))+1)
	 
C      do 300 q=nint(aint(nsign(Y+n1-1,3)/(tii*60))),
C     +		nint(aint(nsign(Y+n1-1,2)/(tii*60))+1)

               do g=1,nf
				    do pp1=j,Nosco
					    matrixgreen(g,pp1)=0
    				enddo
   			   enddo	
	 
      do 300 q=nint(nsign(Y+n1-1,3)/(tii*60)),
     +	nint(nsign(Y+n1-1,2)/(tii*60))
	
                 x=0

c--  filling phase 3
c      print *,'Alex242b4_',Y,j,q	
                  do Kosco=j+1,j+q
				    if(Kosco.le.Nosco)then
						matrixgreen(Y,Kosco)=1
                    else
						x=1
                    exit
                    endif
                  enddo
				  z4=1

      limit=nint(nsign(Y+n1-1,2)/(tii*60))
      limitK=nint(nsign(Y+n1-1,3)/(tii*60))		  
      limit3=limit2+nint(nsign(Y+n1-1,2)/(tii*60))
	  
c      if(nodenumber.eq.5.and.lll*tii.ge.4) 
c     + print *,'Alex2471',x,Kosco,Nosco,limit	
	 
c      if((x.eq.1).or.(Kosco-1.eq.Nosco).or.
c     +	((Kosco-1.lt.Nosco).and.(Kosco.eq.limit)))then
	   
c      if((x.eq.1).or.(Kosco-1.eq.Nosco))then
c      if(nodenumber.eq.5.and.lll*tii.ge.4) print *,
c     + x,Kosco,Nosco,w,nf,j,q,limit,i,b,Y,z3,max1
	  
      if((x.eq.1).or.((Kosco-1.eq.Nosco).and.(i.gt.max1).and.
     + (j.gt.limit2)).or.((i.gt.max1).and.(j-2.ge.limit2).and.
     + (Kosco-3.ge.limit3).and.(q.eq.limit)).or.((i.ge.min1).and.
     + (j-i.ge.limitj).and.(Kosco-j.ge.limitK).and.(nf.le.3)))then

C -- (w.eq.3).and.
	 
C      if(nodenumber.eq.5.and.lll*tii.ge.4) print *,'alex_3','ik=',
C     + ik,'wy=',wy,'maxg=',nsign(ik,2),'ming=',nsign(ik,3)	  

c      write(1,*)'Y=',Y,'Y1=',Y1,'Y2=',Y2,'w=',w,'w1=',w1,'w2=',w2
c     + ,'a=',a,'min1=',min1,'max1=',max1,'wy=',wy	  
	 
			  	    cont=cont+1
c	                write(1,*) cont
c				    write(3,*) cont
c      print *,'Alex2472',n1,n2,Nosco,nf,narcs 	
c      print *,'before RT_DELAY'	
      call RT_DELAY(n1,n2,Nosco,nf,narcs,nodenumber,lll)
c	  ,Kqueue,matrixgreen,mgreen,
c     + matrixvehicle2,
c     + nsign,noofnodes,nu_mv,SatFlowRate,tii) 
c      print *,'after RT_DELAY'		 
C      print *,'Alex248'

	     goto 300
         endif	
		 
c               do g=1,nf
c				    do pp1=j+1,Nosco
c					    matrixgreen(g,pp1)=0
c    				enddo
c   			   enddo	
c       if(salida.eq.1) exit


         Y3=Y
         do 350 w3=1,nf		
				 Y=Y+w3
				 if (Y.gt.nf) then
					z4=-1
					Y=Y-nf
				 endif
		if (Y.NE.Y3) then
	if (nf.ge.4) then

c --  start phase 4
		 
               do g=1,nf
				    do pp1=Kosco,Nosco
					    matrixgreen(g,pp1)=0
    				enddo
   			   enddo	

      do 400 d=nint(aint(nsign(Y+n1-1,3)/(tii*60))),
     +		nint(nsign(Y+n1-1,2)/(tii*60))
            x=0
c --  filling phase 4	 

				    do l=Kosco+1,Kosco+d
					   if (l.le.Nosco) then
						  matrixgreen(Y,l)=1
					   else
					      x=1
					      exit
					   endif
                    enddo
					z5=1
					

      limit=nint(nsign(Y+n1-1,2)/(tii*60))
      limitl=nint(nsign(Y+n1-1,3)/(tii*60))		  
      limit4=limit3+nint(nsign(Y+n1-1,2)/(tii*60))	   
	   
      if((x.eq.1).or.((l-1.eq.Nosco).and.(i.gt.max1).and.
     + (j.gt.limit2).and.(Kosco.gt.limit3)).or.((i.gt.max1).and.
     + (j-2.ge.limit2).and.(l-4.ge.limit4).and.
     + (Kosco-3.ge.limit3).and.(d.eq.limit)).or.((i.ge.min1).and.
     + (j-i.ge.limitj).and.(Kosco-j.ge.limitK).and.(nf.le.4).and.
     + (l-Kosco.ge.limitl)))then	 
	 
c      if((x.eq.1).or.(Kosco-1.eq.Nosco).or.((w.eq.nf).and.
c     + (Kosco.gt.j+q).and.(Kosco-3.eq.limit).and.(j.gt.i+b)
c     +	.and.((Y.eq.nf).or.(z3.eq.-1))))then
	 
c      if((x.eq.1).or.(l-1.eq.Nosco))then
	  
						cont=cont+1
c						write(1,*) cont
c				        write(3,*) cont
c      print *,'Alex249',n1,n2,Nosco,nf,narcs 
c      print *,'before RT_DELAY'	
      call RT_DELAY(n1,n2,Nosco,nf,narcs,nodenumber,lll)
c	  ,Kqueue,matrixgreen,mgreen,
c     + matrixvehicle2,
c     + nsign,noofnodes,nu_mv,SatFlowRate,tii) 
c      print *,'after RT_DELAY'	
C      print *,'Alex250'
c				write(1,10) ((matrixgreen(g,h), h=1, Nosco), g=1, nf)
c			write(3,11) ((matrixvehicle(g,h), h=1, Nosco), g=1, nf)
         goto 400
         endif	
	   
				Y4=Y
				do 450 w4=1,nf

				     Y=Y+w4
				     if (Y.gt.nf) then
					    z5=-1
					    Y=Y-nf
				     endif
				if (Y.NE.Y4) then
      if (nf.ge.5) then

c --  start phase 5
		 
               do g=1,nf
				    do pp1=l,Nosco
					    matrixgreen(g,pp1)=0
    				enddo
   			   enddo	
			   
      do 500 e=nint(aint(nsign(Y+n1-1,3)/(tii*60))),
     +		nint(nsign(Y+n1-1,2)/(tii*60))
					x=0
	
c --  filling phase 5	 

				    do ll=l+1,l+e
					   if (ll.le.Nosco) then
						  matrixgreen(Y,ll)=1
					   else
					      x=1
					      exit
					   endif
					enddo
					z6=1

      limit=nint(nsign(Y+n1-1,2)/(tii*60))
      limitll=nint(nsign(Y+n1-1,3)/(tii*60))		  
      limit5=limit4+nint(nsign(Y+n1-1,2)/(tii*60))	   
	   
      if((x.eq.1).or.((l-1.eq.Nosco).and.(i.gt.max1).and.
     + (j.gt.limit2).and.(Kosco.gt.limit3)).or.((i.gt.max1).and.
     + (j-2.ge.limit2).and.(l-4.ge.limit4).and.(ll-5.ge.limit5).and.
     + (Kosco-3.ge.limit3).and.(e.eq.limit)).or.((i.ge.min1).and.
     + (j-i.ge.limitj).and.(Kosco-j.ge.limitK).and.(nf.le.4).and.
     + (l-Kosco.ge.limitl).and.(ll-l.ge.limitll)))then	
	 
c      if((x.eq.1).or.(ll-1.eq.Nosco))then
	  
						cont=cont+1
c						write(1,*) cont
c						write(3,*) cont
c      print *,'Alex251',n1,n2,Nosco,nf,narcs 
c      print *,'before RT_DELAY'	
      call RT_DELAY(n1,n2,Nosco,nf,narcs,nodenumber,lll)
c	  ,Kqueue,matrixgreen,mgreen,
c     + matrixvehicle2,
c     + nsign,noofnodes,nu_mv,SatFlowRate,tii) 
c      print *,'after RT_DELAY'	
C      print *,'Alex252'	 
c				write(1,10) ((matrixgreen(g,h), h=1, Nosco), g=1, nf)
c			write(3,11) ((matrixvehicle(g,h), h=1, Nosco), g=1, nf)
         goto 500
         endif	

	   
			Y5=Y
			do 550 w5=1,nf
				     Y=Y+w5
				     if (Y.gt.nf) then
					    z6=-1
					    Y=Y-nf
				     endif
			if (Y.NE.Y5) then
	if (nf.ge.6) then

c--   start phase 6
		 
               do g=1,nf
				    do pp1=ll,Nosco
					    matrixgreen(g,pp1)=0
    				enddo
   			   enddo
			   
      do 600 f=nint(aint(nsign(Y+n1-1,3)/(tii*60))),
     +		nint(nsign(Y+n1-1,2)/(tii*60))
					    x=0
	
c --   filling phase 6	 

				    do m=ll+1,ll+f
					   if (m.le.Nosco) then
						  matrixgreen(Y,m)=1
					   else
					      x=1
					      exit
					   endif
					enddo
					z7=1
					
      limit=nint(nsign(Y+n1-1,2)/(tii*60))
      limitm=nint(nsign(Y+n1-1,3)/(tii*60))		  
      limit6=limit5+nint(nsign(Y+n1-1,2)/(tii*60))	   
	   
      if((x.eq.1).or.((l-1.eq.Nosco).and.(i.gt.max1).and.
     + (j.gt.limit2).and.(Kosco.gt.limit3)).or.((i.gt.max1).and.
     + (j-2.ge.limit2).and.(l-4.ge.limit4).and.(ll-5.ge.limit5).and.
     + (m-6.ge.limit6).and. 
     + (Kosco-3.ge.limit3).and.(f.eq.limit)).or.((i.ge.min1).and.
     + (j-i.ge.limitj).and.(Kosco-j.ge.limitK).and.(nf.le.4).and.
     + (l-Kosco.ge.limitl).and.(ll-l.ge.limitll).and.
     + (m-ll.ge.limitm))) then	
	 
c      if((x.eq.1).or.(m-1.eq.Nosco))then
						cont=cont+1
c						write(1,*) cont
c				        write(3,*) cont
c      print *,'Alex253',n1,n2,Nosco,nf,narcs 
c      print *,'before RT_DELAY'	
      call RT_DELAY(n1,n2,Nosco,nf,narcs,nodenumber,lll)
c	  ,Kqueue,matrixgreen,mgreen,
c     + matrixvehicle2,
c     + nsign,noofnodes,nu_mv,SatFlowRate,tii) 
c      print *,'after RT_DELAY'	
C      print *,'Alex254'
c				write(1,10) ((matrixgreen(g,h), h=1, Nosco), g=1, nf)
c			write(3,11) ((matrixvehicle(g,h), h=1, Nosco), g=1, nf) 
         goto 600
         endif	
	

			Y6=Y
			do 650 w6=1,nf
				     Y=Y+w6
				     if (Y.gt.nf) then
					    z7=-1
					    Y=Y-nf
				     endif
			if (Y.NE.Y6) then

	if (nf.ge.7) then

c --   start phase 7
		 
               do g=1,nf
				    do pp1=m,Nosco
					    matrixgreen(g,pp1)=0
    				enddo
   			   enddo	
			   
      do 700 r=nint(aint(nsign(Y+n1-1,3)/(tii*60))),
     +		nint(nsign(Y+n1-1,2)/(tii*60))
					    x=0
c --   filling phase 7	 

				       do o=m+1,m+r
					      if (o.le.Nosco) then
						     matrixgreen(Y,o)=1
					      else
					         x=1
					      exit
					      endif
					  enddo
					  
      limit=nint(nsign(Y+n1-1,2)/(tii*60))
      limito=nint(nsign(Y+n1-1,3)/(tii*60))		  
      limit7=limit7+nint(nsign(Y+n1-1,2)/(tii*60))	   
	   
      if((x.eq.1).or.((l-1.eq.Nosco).and.(i.gt.max1).and.
     + (j.gt.limit2).and.(Kosco.gt.limit3)).or.((i.gt.max1).and.
     + (j-2.ge.limit2).and.(l-4.ge.limit4).and.(ll-5.ge.limit5).and.
     + (m-6.ge.limit6).and.(o-7.ge.limit7).and. 
     + (Kosco-3.ge.limit3).and.(r.eq.limit)).or.((i.ge.min1).and.
     + (j-i.ge.limitj).and.(Kosco-j.ge.limitK).and.(nf.le.4).and.
     + (l-Kosco.ge.limitl).and.(ll-l.ge.limitll).and.
     + (m-ll.ge.limitm).and.(o-m.ge.limito))) then	
	 
c      if((x.eq.1).or.(o-1.eq.Nosco))then
						cont=cont+1
c    						write(1,*) cont
c      print *,'Alex255',n1,n2,Nosco,nf,narcs 
c      print *,'before RT_DELAY'	
      call RT_DELAY(n1,n2,Nosco,nf,narcs,nodenumber,lll)
c	  ,Kqueue,matrixgreen,mgreen,
c     + matrixvehicle2,
c     + nsign,noofnodes,nu_mv,SatFlowRate,tii) 
c      print *,'after RT_DELAY'	
C      print *,'Alex256'
c				write(1,10) ((matrixgreen(g,h), h=1, Nosco), g=1, nf)
c			write(3,11) ((matrixvehicle(g,h), h=1, Nosco), g=1, nf)
         goto 700
         endif	
		
700             continue
         endif
       endif
      Y=Y6	   
650   continue
c      Y=Y6
600             continue   
       endif
      endif
      Y=Y5	  
550   continue
c      Y=Y5
500			continue
       endif
       endif
       Y=Y4		   
450   continue
c       Y=Y4				
400   continue
	
       endif
      endif
      Y=Y3	  
350   continue					
c      Y=Y3
300	  continue

      endif 
      endif
      Y=Y2	  
250   continue
c      Y=Y2
200   continue
      endif
      endif
      Y=Y1	  
150   continue
c      Y=Y1
100	  continue

15	   continue
	
C      print *,'end RT_OSCO'
c      write(1,*) 'optimal phase secuence',delaycont,mindelay
C     + ,'ik=',ik,'wy=',wy,'maxg=',nsign(ik,2),'ming=',nsign(ik,3)	  
c      do g=1,nf
c      write(1,*) (mgreen(g,h), h=1, Nosco)
c      enddo	  
	  

C      print *,'end RT_OSCO2'			
c	  write(3,*) cont2
c	  write(6,*) cont

c	  write(4,10) ((matrixgreen(g,h), h=1, Nosco), g=1, nf)
c	  write(3,11) ((matrixvehicle2(g,h), h=1, Nosco), g=1, nf)

10    format(11i4)
11    format(13i4)
c      print *,'end RT_OSCO3'
      deallocate(matrixvehicle2,stat=error)
      deallocate(matrixvehicle1,stat=error)	  
c      print *,'end RT_OSCO4'

      return
      end
	   